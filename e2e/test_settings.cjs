/**
 * Test Settings, Export, Dark Mode, Research, and Notifications.
 * Run: node e2e/test_settings.cjs
 */
const { chromium } = require('playwright');

const DIR = 'test-evidence';
const BASE = 'http://127.0.0.1:5001';

const results = [];
function log(test, status, detail) {
    results.push({ test, status, detail });
    const tag = status === 'PASS' ? '\x1b[32mPASS\x1b[0m' : '\x1b[31mFAIL\x1b[0m';
    console.log(`  [${tag}] ${test}: ${detail}`);
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

    // ─── SETUP ───────────────────────────────────────────────
    console.log('\n=== SETUP ===');

    console.log('  Loading homepage...');
    await page.goto(BASE + '/', { waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForTimeout(2000);

    // Dismiss driver.js tour
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(500);

    // Get CSRF token
    const csrf = await page.evaluate(() => {
        const m = document.querySelector('meta[name="csrf-token"]');
        return m ? m.getAttribute('content') : '';
    });
    if (!csrf) {
        console.log('  ERROR: No CSRF token found');
        await browser.close();
        process.exit(1);
    }
    console.log('  CSRF token acquired');

    // Create test project with seed categories
    console.log('  Creating test project...');
    const projResp = await page.evaluate(async (token) => {
        const r = await fetch('/api/projects', {
            method: 'POST',
            headers: { 'X-CSRF-Token': token, 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: 'Settings Test ' + Date.now(),
                purpose: 'Test settings, export, dark mode, notifications',
                seed_categories: 'Digital Health\nInsurTech\nHealthcare AI'
            })
        });
        return r.json();
    }, csrf);

    let pid = projResp.id || projResp.project_id;
    if (!pid) {
        console.log('  Project creation returned no ID, using existing project...');
        const projects = await page.evaluate(async (token) => {
            const r = await fetch('/api/projects', { headers: { 'X-CSRF-Token': token } });
            return r.json();
        }, csrf);
        if (projects && projects.length > 0) {
            pid = projects[0].id;
            console.log('  Using existing project:', pid);
        } else {
            console.log('  ERROR: No projects available');
            await browser.close();
            process.exit(1);
        }
    } else {
        console.log('  Project created: ID', pid);
    }

    // Add 3 test companies with unique URLs
    console.log('  Adding 3 test companies...');
    const companies = [
        { name: 'Oscar Health', url: 'https://oscar.com', hq_city: 'New York', hq_country: 'US', geography: 'United States', category_name: 'Digital Health' },
        { name: 'Babylon Health', url: 'https://babylon.com', hq_city: 'London', hq_country: 'UK', geography: 'United Kingdom', category_name: 'Healthcare AI' },
        { name: 'Lemonade', url: 'https://lemonade.com', hq_city: 'New York', hq_country: 'US', geography: 'United States', category_name: 'InsurTech' },
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
    console.log('  Added 3 companies');

    // Select the project
    console.log('  Selecting project...');
    await page.evaluate((id) => { selectProject(id); }, pid);
    await page.waitForTimeout(3000);

    // Dismiss tour again after project selection
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(500);
    console.log('  Setup complete.\n');

    // Helper: dismiss tour
    async function dismissTour() {
        await page.evaluate(() => {
            if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
            document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
        });
        await page.waitForTimeout(300);
    }

    // ─── TEST A: Settings Tab ────────────────────────────────
    console.log('=== TEST A: Settings Tab ===');
    try {
        await page.evaluate(() => showTab('settings'));
        await page.waitForTimeout(2000);
        await dismissTour();

        await page.screenshot({ path: DIR + '/feature_settings_tab.png', fullPage: false });
        console.log('  Screenshot saved: feature_settings_tab.png');

        // Check what settings elements are visible
        const settingsInfo = await page.evaluate(() => {
            const tab = document.getElementById('tab-settings');
            if (!tab) return { error: 'tab-settings element not found' };

            const heading = tab.querySelector('h2');
            const sections = tab.querySelectorAll('.settings-section');
            const sectionHeadings = [...tab.querySelectorAll('.section-heading')].map(h => h.textContent.trim());
            const inputs = [...tab.querySelectorAll('input')].map(i => ({
                type: i.type,
                id: i.id || '(no id)',
                placeholder: i.placeholder || '',
                visible: i.offsetWidth > 0
            }));
            const buttons = [...tab.querySelectorAll('button')].map(b => ({
                text: b.textContent.trim().substring(0, 40),
                visible: b.offsetWidth > 0
            }));
            const selects = [...tab.querySelectorAll('select')].map(s => ({
                id: s.id || '(no id)',
                visible: s.offsetWidth > 0
            }));
            const aiCards = [...tab.querySelectorAll('.ai-setup-card')].map(c => {
                const strong = c.querySelector('strong');
                return strong ? strong.textContent.trim() : '(unknown)';
            });

            return {
                headingText: heading ? heading.textContent.trim() : '(none)',
                sectionCount: sections.length,
                sectionHeadings,
                inputCount: inputs.length,
                inputs,
                buttonCount: buttons.length,
                buttons: buttons.filter(b => b.visible),
                selectCount: selects.length,
                selects,
                aiCards,
                tabHidden: tab.classList.contains('hidden'),
                tabHeight: tab.offsetHeight,
                tabWidth: tab.offsetWidth,
            };
        });

        console.log('  Settings tab heading:', settingsInfo.headingText);
        console.log('  Sections (' + settingsInfo.sectionCount + '):', settingsInfo.sectionHeadings.join(', '));
        console.log('  AI Backend cards:', settingsInfo.aiCards.join(', '));
        console.log('  Inputs (' + settingsInfo.inputCount + '):');
        settingsInfo.inputs.forEach(i => console.log('    -', i.id, '(' + i.type + ')', i.placeholder ? '"' + i.placeholder + '"' : ''));
        console.log('  Selects (' + settingsInfo.selectCount + '):');
        settingsInfo.selects.forEach(s => console.log('    -', s.id, 'visible:', s.visible));
        console.log('  Visible buttons (' + settingsInfo.buttons.length + '):');
        settingsInfo.buttons.forEach(b => console.log('    -', b.text));

        const settingsRendered = settingsInfo.tabHeight > 0 && !settingsInfo.tabHidden && settingsInfo.sectionCount >= 2;
        log('A - Settings Tab renders', settingsRendered ? 'PASS' : 'FAIL',
            settingsRendered ? `${settingsInfo.sectionCount} sections, ${settingsInfo.inputCount} inputs, ${settingsInfo.buttons.length} visible buttons`
                : `tabHidden=${settingsInfo.tabHidden}, height=${settingsInfo.tabHeight}, sections=${settingsInfo.sectionCount}`);
    } catch (err) {
        log('A - Settings Tab renders', 'FAIL', err.message);
    }

    // ─── TEST B: Dark Mode Toggle ────────────────────────────
    console.log('\n=== TEST B: Dark Mode Toggle ===');
    try {
        // Check initial theme state
        const beforeTheme = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
        console.log('  Theme before toggle:', JSON.stringify(beforeTheme));

        // Find and click the dark mode toggle button
        const toggleFound = await page.evaluate(() => {
            const btns = document.querySelectorAll('.theme-toggle');
            return btns.length;
        });
        console.log('  Theme toggle buttons found:', toggleFound);

        // Click via function call (more reliable)
        await page.evaluate(() => toggleTheme());
        await page.waitForTimeout(1000);

        await page.screenshot({ path: DIR + '/feature_dark_mode.png', fullPage: false });
        console.log('  Screenshot saved: feature_dark_mode.png');

        // Check if dark mode is applied
        const darkModeInfo = await page.evaluate(() => {
            const html = document.documentElement;
            const theme = html.getAttribute('data-theme');
            const bodyClasses = document.body.className;
            // Check some CSS custom property changes (background color)
            const bodyBg = getComputedStyle(document.body).backgroundColor;
            const bodyColor = getComputedStyle(document.body).color;
            // Check toggle icon changed
            const toggleIcon = document.querySelector('.theme-toggle .material-symbols-outlined');
            const iconText = toggleIcon ? toggleIcon.textContent.trim() : '(none)';
            return { theme, bodyClasses, bodyBg, bodyColor, iconText };
        });

        console.log('  data-theme attribute:', darkModeInfo.theme);
        console.log('  Body background:', darkModeInfo.bodyBg);
        console.log('  Body text color:', darkModeInfo.bodyColor);
        console.log('  Toggle icon text:', darkModeInfo.iconText);

        const isDark = darkModeInfo.theme === 'dark';
        log('B - Dark Mode toggle activates', isDark ? 'PASS' : 'FAIL',
            isDark ? `data-theme="dark", icon="${darkModeInfo.iconText}", bg=${darkModeInfo.bodyBg}`
                : `Expected data-theme="dark", got "${darkModeInfo.theme}"`);
    } catch (err) {
        log('B - Dark Mode toggle activates', 'FAIL', err.message);
    }

    // ─── TEST C: Dark Mode on Different Tabs ─────────────────
    console.log('\n=== TEST C: Dark Mode on Different Tabs ===');
    try {
        // Companies tab in dark mode
        await page.evaluate(() => showTab('companies'));
        await page.waitForTimeout(1000);
        await dismissTour();
        await page.screenshot({ path: DIR + '/feature_dark_companies.png', fullPage: false });
        console.log('  Screenshot saved: feature_dark_companies.png');
        const companiesDark = await page.evaluate(() => {
            const tab = document.getElementById('tab-companies');
            const theme = document.documentElement.getAttribute('data-theme');
            return { visible: tab && !tab.classList.contains('hidden') && tab.offsetHeight > 0, theme };
        });
        log('C1 - Companies tab in dark mode', companiesDark.visible && companiesDark.theme === 'dark' ? 'PASS' : 'FAIL',
            `visible=${companiesDark.visible}, theme=${companiesDark.theme}`);

        // Taxonomy tab in dark mode
        await page.evaluate(() => showTab('taxonomy'));
        await page.waitForTimeout(1000);
        await dismissTour();
        await page.screenshot({ path: DIR + '/feature_dark_taxonomy.png', fullPage: false });
        console.log('  Screenshot saved: feature_dark_taxonomy.png');
        const taxonomyDark = await page.evaluate(() => {
            const tab = document.getElementById('tab-taxonomy');
            const theme = document.documentElement.getAttribute('data-theme');
            return { visible: tab && !tab.classList.contains('hidden') && tab.offsetHeight > 0, theme };
        });
        log('C2 - Taxonomy tab in dark mode', taxonomyDark.visible && taxonomyDark.theme === 'dark' ? 'PASS' : 'FAIL',
            `visible=${taxonomyDark.visible}, theme=${taxonomyDark.theme}`);

        // Map tab in dark mode
        await page.evaluate(() => showTab('map'));
        await page.waitForTimeout(1000);
        await dismissTour();
        await page.screenshot({ path: DIR + '/feature_dark_map.png', fullPage: false });
        console.log('  Screenshot saved: feature_dark_map.png');
        const mapDark = await page.evaluate(() => {
            const tab = document.getElementById('tab-map');
            const theme = document.documentElement.getAttribute('data-theme');
            return { visible: tab && !tab.classList.contains('hidden') && tab.offsetHeight > 0, theme };
        });
        log('C3 - Map tab in dark mode', mapDark.visible && mapDark.theme === 'dark' ? 'PASS' : 'FAIL',
            `visible=${mapDark.visible}, theme=${mapDark.theme}`);
    } catch (err) {
        log('C - Dark Mode on tabs', 'FAIL', err.message);
    }

    // ─── TEST D: Export Tab ──────────────────────────────────
    console.log('\n=== TEST D: Export Tab ===');
    try {
        // Toggle dark mode back OFF first
        await page.evaluate(() => {
            const current = document.documentElement.getAttribute('data-theme');
            if (current === 'dark') toggleTheme();
        });
        await page.waitForTimeout(500);
        const themeAfterOff = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
        console.log('  Theme after toggling OFF:', themeAfterOff);

        await page.evaluate(() => showTab('export'));
        await page.waitForTimeout(2000);
        await dismissTour();

        await page.screenshot({ path: DIR + '/feature_export_tab.png', fullPage: false });
        console.log('  Screenshot saved: feature_export_tab.png');

        // Check export options
        const exportInfo = await page.evaluate(() => {
            const tab = document.getElementById('tab-export');
            if (!tab) return { error: 'tab-export not found' };

            const cards = [...tab.querySelectorAll('.export-card')];
            const exportOptions = cards.map(card => {
                const h3 = card.querySelector('h3');
                const p = card.querySelector('p');
                const btn = card.querySelector('a.btn, button.btn');
                return {
                    name: h3 ? h3.textContent.trim() : '(no title)',
                    description: p ? p.textContent.trim() : '',
                    buttonText: btn ? btn.textContent.trim() : '(no button)',
                    buttonEnabled: btn ? !btn.disabled : false,
                    buttonVisible: btn ? btn.offsetWidth > 0 : false,
                };
            });

            // Share section
            const shareSection = tab.querySelector('.share-section');
            const shareLinkInput = tab.querySelector('#shareLinkLabel');
            const shareBtn = tab.querySelector('.share-section .primary-btn');

            // Notification settings
            const notifSection = tab.querySelector('.notification-settings');
            const slackInput = tab.querySelector('#slackWebhook');

            return {
                tabHidden: tab.classList.contains('hidden'),
                tabHeight: tab.offsetHeight,
                exportCardCount: cards.length,
                exportOptions,
                hasShareSection: !!shareSection,
                hasShareInput: !!shareLinkInput,
                hasShareBtn: !!shareBtn,
                hasNotifSettings: !!notifSection,
                hasSlackInput: !!slackInput,
            };
        });

        console.log('  Export cards (' + exportInfo.exportCardCount + '):');
        exportInfo.exportOptions.forEach(opt => {
            console.log('    -', opt.name, '|', opt.buttonText, '| enabled:', opt.buttonEnabled, '| visible:', opt.buttonVisible);
        });
        console.log('  Share section present:', exportInfo.hasShareSection);
        console.log('  Notification settings present:', exportInfo.hasNotifSettings);
        console.log('  Slack webhook input present:', exportInfo.hasSlackInput);

        const exportOk = !exportInfo.tabHidden && exportInfo.exportCardCount >= 5;
        log('D - Export Tab renders', exportOk ? 'PASS' : 'FAIL',
            exportOk ? `${exportInfo.exportCardCount} export options available`
                : `tabHidden=${exportInfo.tabHidden}, cards=${exportInfo.exportCardCount}`);

        // Check export buttons are clickable (enabled and visible)
        const clickableCount = exportInfo.exportOptions.filter(o => o.buttonEnabled && o.buttonVisible).length;
        log('D - Export buttons clickable', clickableCount >= 5 ? 'PASS' : 'FAIL',
            `${clickableCount}/${exportInfo.exportCardCount} export buttons are enabled and visible`);
    } catch (err) {
        log('D - Export Tab', 'FAIL', err.message);
    }

    // ─── TEST E: Research Tab ────────────────────────────────
    console.log('\n=== TEST E: Research Tab ===');
    try {
        // Research tab uses 'reports' as the tab ID
        await page.evaluate(() => showTab('reports'));
        await page.waitForTimeout(2000);
        await dismissTour();

        await page.screenshot({ path: DIR + '/feature_research_tab.png', fullPage: false });
        console.log('  Screenshot saved: feature_research_tab.png');

        // Check research UI elements
        const researchInfo = await page.evaluate(() => {
            const tab = document.getElementById('tab-reports');
            if (!tab) return { error: 'tab-reports not found' };

            // Research mode toggle buttons
            const modeToggle = tab.querySelector('.research-mode-toggle');
            const modeButtons = [...(modeToggle ? modeToggle.querySelectorAll('button') : [])].map(b => ({
                text: b.textContent.trim(),
                active: b.classList.contains('active'),
                id: b.id || '(no id)',
            }));

            // Quick Report section
            const reportSection = tab.querySelector('#researchModeReport');
            const reportHidden = reportSection ? reportSection.classList.contains('hidden') : true;

            // Deep Dive section
            const deepDiveSection = tab.querySelector('#researchModeDeepDive');
            const deepDiveHidden = deepDiveSection ? deepDiveSection.classList.contains('hidden') : true;

            // Research prompt elements
            const promptTextarea = tab.querySelector('#researchPrompt');
            const researchBtn = tab.querySelector('#researchBtn');
            const scopeType = tab.querySelector('#researchScopeType');
            const titleInput = tab.querySelector('#researchTitle');
            const modelSelect = tab.querySelector('#researchModelSelect');
            const templateBtns = tab.querySelector('#researchTemplateButtons');

            // All visible inputs/buttons/selects
            const allInputs = [...tab.querySelectorAll('input, textarea, select')].map(el => ({
                tag: el.tagName.toLowerCase(),
                id: el.id || '(no id)',
                type: el.type || '',
                placeholder: el.placeholder || '',
                visible: el.offsetWidth > 0,
            }));
            const allButtons = [...tab.querySelectorAll('button')].filter(b => b.offsetWidth > 0).map(b => ({
                text: b.textContent.trim().substring(0, 50),
                id: b.id || '(no id)',
            }));

            return {
                tabHidden: tab.classList.contains('hidden'),
                tabHeight: tab.offsetHeight,
                modeButtons,
                reportSectionVisible: !reportHidden,
                deepDiveSectionVisible: !deepDiveHidden,
                hasPromptTextarea: !!promptTextarea,
                hasResearchBtn: !!researchBtn,
                hasScopeType: !!scopeType,
                hasTitleInput: !!titleInput,
                hasModelSelect: !!modelSelect,
                hasTemplateButtons: !!templateBtns,
                allInputs,
                allButtons,
            };
        });

        console.log('  Research tab visible:', !researchInfo.tabHidden, '| height:', researchInfo.tabHeight);
        console.log('  Mode buttons:');
        researchInfo.modeButtons.forEach(b => console.log('    -', b.text, '| active:', b.active, '| id:', b.id));
        console.log('  Quick Report visible:', researchInfo.reportSectionVisible);
        console.log('  Deep Dive visible:', researchInfo.deepDiveSectionVisible);
        console.log('  UI elements:');
        console.log('    - Prompt textarea:', researchInfo.hasPromptTextarea);
        console.log('    - Research button:', researchInfo.hasResearchBtn);
        console.log('    - Scope selector:', researchInfo.hasScopeType);
        console.log('    - Title input:', researchInfo.hasTitleInput);
        console.log('    - Model selector:', researchInfo.hasModelSelect);
        console.log('    - Template buttons area:', researchInfo.hasTemplateButtons);
        console.log('  All visible inputs/textareas/selects:');
        researchInfo.allInputs.forEach(i => console.log('    -', i.tag, i.id, i.type, i.placeholder ? '"' + i.placeholder + '"' : '', 'visible:', i.visible));
        console.log('  All visible buttons:');
        researchInfo.allButtons.forEach(b => console.log('    -', b.text, '(' + b.id + ')'));

        const researchOk = !researchInfo.tabHidden && researchInfo.tabHeight > 0 && researchInfo.modeButtons.length >= 2;
        log('E - Research Tab renders', researchOk ? 'PASS' : 'FAIL',
            researchOk ? `${researchInfo.modeButtons.length} mode buttons, Quick Report visible=${researchInfo.reportSectionVisible}`
                : `tabHidden=${researchInfo.tabHidden}, height=${researchInfo.tabHeight}`);

        // Switch to Deep Dive mode and check
        await page.evaluate(() => {
            if (typeof switchResearchMode === 'function') switchResearchMode('deepdive');
        });
        await page.waitForTimeout(1000);

        const deepDiveVisible = await page.evaluate(() => {
            const dd = document.getElementById('researchModeDeepDive');
            return dd ? !dd.classList.contains('hidden') && dd.offsetHeight > 0 : false;
        });
        log('E - Deep Dive mode switch', deepDiveVisible ? 'PASS' : 'FAIL',
            deepDiveVisible ? 'Deep Dive section is visible after mode switch' : 'Deep Dive section not visible');

    } catch (err) {
        log('E - Research Tab', 'FAIL', err.message);
    }

    // ─── TEST F: Notification Bell ───────────────────────────
    console.log('\n=== TEST F: Notification Bell ===');
    try {
        // Check for notification bell in the header
        const bellInfo = await page.evaluate(() => {
            const bell = document.querySelector('.notification-bell');
            const panel = document.getElementById('notificationPanel');
            const badge = document.getElementById('bellBadge');
            return {
                bellFound: !!bell,
                bellVisible: bell ? bell.offsetWidth > 0 : false,
                panelFound: !!panel,
                panelHidden: panel ? panel.classList.contains('hidden') : true,
                badgeFound: !!badge,
                badgeText: badge ? badge.textContent.trim() : '',
            };
        });

        console.log('  Bell button found:', bellInfo.bellFound, '| visible:', bellInfo.bellVisible);
        console.log('  Panel found:', bellInfo.panelFound, '| hidden:', bellInfo.panelHidden);
        console.log('  Badge found:', bellInfo.badgeFound, '| text:', bellInfo.badgeText);

        if (bellInfo.bellFound && bellInfo.bellVisible) {
            // Click the notification bell
            await page.evaluate(() => {
                if (typeof toggleNotificationPanel === 'function') {
                    toggleNotificationPanel();
                } else {
                    const bell = document.querySelector('.notification-bell');
                    if (bell) bell.click();
                }
            });
            await page.waitForTimeout(1000);

            await page.screenshot({ path: DIR + '/feature_notifications.png', fullPage: false });
            console.log('  Screenshot saved: feature_notifications.png');

            // Check if panel opened
            const panelState = await page.evaluate(() => {
                const panel = document.getElementById('notificationPanel');
                if (!panel) return { error: 'panel not found' };
                const items = panel.querySelectorAll('.notif-item, .notification-item');
                const emptyMsg = panel.querySelector('.notif-empty, .no-notifications, .hint-text');
                return {
                    hidden: panel.classList.contains('hidden'),
                    height: panel.offsetHeight,
                    width: panel.offsetWidth,
                    itemCount: items.length,
                    hasEmptyMessage: !!emptyMsg,
                    emptyMessageText: emptyMsg ? emptyMsg.textContent.trim().substring(0, 60) : '',
                    innerHTML: panel.innerHTML.substring(0, 200),
                };
            });

            console.log('  Panel hidden after click:', panelState.hidden);
            console.log('  Panel size:', panelState.width, 'x', panelState.height);
            console.log('  Notification items:', panelState.itemCount);
            console.log('  Has empty message:', panelState.hasEmptyMessage, panelState.emptyMessageText);

            const panelOpened = !panelState.hidden && panelState.height > 0;
            log('F - Notification panel opens', panelOpened ? 'PASS' : 'FAIL',
                panelOpened ? `Panel visible (${panelState.width}x${panelState.height}), ${panelState.itemCount} items`
                    : `hidden=${panelState.hidden}, height=${panelState.height}`);
        } else {
            // Bell not visible - take screenshot anyway
            await page.screenshot({ path: DIR + '/feature_notifications.png', fullPage: false });
            console.log('  Screenshot saved: feature_notifications.png');
            log('F - Notification bell found', bellInfo.bellFound ? 'PASS' : 'FAIL',
                bellInfo.bellFound ? 'Bell exists but not visible (may be on project view only)' : 'No .notification-bell element found');
        }
    } catch (err) {
        log('F - Notification Bell', 'FAIL', err.message);
    }

    // ─── SUMMARY ─────────────────────────────────────────────
    console.log('\n' + '='.repeat(60));
    console.log('=== RESULTS SUMMARY ===');
    console.log('='.repeat(60));
    let passCount = 0;
    let failCount = 0;
    results.forEach(r => {
        const tag = r.status === 'PASS' ? '\x1b[32mPASS\x1b[0m' : '\x1b[31mFAIL\x1b[0m';
        if (r.status === 'PASS') passCount++; else failCount++;
        console.log(`  [${tag}] ${r.test}`);
        console.log(`         ${r.detail}`);
    });
    console.log('='.repeat(60));
    console.log(`  Total: ${passCount + failCount} | Pass: ${passCount} | Fail: ${failCount}`);
    console.log('='.repeat(60));

    // Console errors
    console.log('\n=== Console Errors (' + consoleErrors.length + ') ===');
    if (consoleErrors.length > 0) {
        consoleErrors.slice(0, 20).forEach(e => console.log('  ', e));
        if (consoleErrors.length > 20) console.log('  ... and', consoleErrors.length - 20, 'more');
    } else {
        console.log('  None detected');
    }

    await browser.close();
    console.log('\nAll screenshots saved to ' + DIR + '/');
    console.log('Done.');
})().catch(e => {
    console.error('FATAL:', e.message);
    process.exit(1);
});
