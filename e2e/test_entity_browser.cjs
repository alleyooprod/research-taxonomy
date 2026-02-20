/**
 * E2E Test: Entity Browser CRUD Operations
 * Tests: entity browser activation, create/read/update/delete entities,
 *        entity type switching, detail panel, search, bulk selection.
 * Requires a project with a multi-type schema (market_analysis template).
 * Run: node e2e/test_entity_browser.cjs
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
           && typeof showTab === 'function'
           && typeof loadCompanies === 'function',
        { timeout: 15000 }
    );
    await page.waitForFunction(
        () => {
            const grid = document.getElementById('projectGrid');
            return grid && grid.children.length > 0;
        },
        { timeout: 10000 }
    ).catch(() => {});
    await page.waitForTimeout(500);
    await dismissTour(page);
    await page.waitForTimeout(300);
}

/**
 * Confirm a native confirm dialog (the app's custom #confirmSheet).
 * The deleteEntity function uses showNativeConfirm which shows #confirmSheet.
 */
async function confirmNativeDialog(page) {
    await page.waitForTimeout(500);
    const confirmed = await page.evaluate(() => {
        const overlay = document.getElementById('confirmSheet');
        if (!overlay || overlay.style.display === 'none') return false;
        const btn = document.getElementById('confirmSheetConfirm');
        if (btn) { btn.click(); return true; }
        return false;
    });
    await page.waitForTimeout(500);
    return confirmed;
}

(async () => {
    console.log('=== Entity Browser E2E Test ===\n');

    const browser = await chromium.launch({ headless: true });
    const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
    const page = await ctx.newPage();

    // Collect console errors
    const consoleErrors = [];
    page.on('console', msg => {
        if (msg.type() === 'error') consoleErrors.push(msg.text());
    });

    // ---- Setup: Load page, create project with multi-type schema, select it ----
    console.log('--- Setup ---');
    console.log('  Loading page...');
    await page.goto(BASE + '/', { waitUntil: 'networkidle', timeout: 20000 });
    await waitForAppReady(page);

    const csrf = await getCSRF(page);
    if (!csrf) {
        console.log('  FATAL: No CSRF token found');
        await browser.close();
        process.exit(1);
    }
    console.log('  CSRF token acquired');

    // Create a project with market_analysis template (multi-type: Company, Product, Feature, Plan)
    const projName = 'Entity Browser Test ' + Date.now();
    console.log(`  Creating project: ${projName}`);
    const projResp = await page.evaluate(async (name) => {
        const csrf = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
        const r = await fetch('/api/projects', {
            method: 'POST',
            headers: { 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name,
                purpose: 'E2E test for entity browser CRUD',
                seed_categories: 'InsurTech\nHealthTech',
                template: 'market_analysis',
            })
        });
        return { status: r.status, body: await r.json() };
    }, projName);

    const pid = projResp.body.id || projResp.body.project_id;
    if (!pid) {
        console.log('  FATAL: Project creation failed:', JSON.stringify(projResp));
        await browser.close();
        process.exit(1);
    }
    console.log(`  Project created with ID: ${pid}`);

    // Select the project
    await page.evaluate(
        (args) => selectProject(args.id, args.name),
        { id: pid, name: projName }
    );
    await page.waitForTimeout(3000);
    await dismissTour(page);
    await page.waitForTimeout(500);

    // Switch to companies/entities tab
    await page.evaluate(() => showTab('companies'));
    await page.waitForTimeout(2000);
    await dismissTour(page);
    console.log('  Project selected, companies tab active\n');

    // =========================================================================
    // TEST A -- Entity Browser Activation
    // =========================================================================
    console.log('--- TEST A: Entity Browser Activation ---');
    try {
        await page.screenshot({ path: path.join(DIR, 'entity_browser_initial.png') });
        console.log('  Screenshot: entity_browser_initial.png');

        const browserInfo = await page.evaluate(() => {
            const entityBrowser = document.getElementById('entityBrowser');
            const companyView = document.getElementById('companyViewWrapper');
            const typeBar = document.getElementById('entityTypeBar');
            const typeButtons = document.querySelectorAll('.entity-type-btn');
            const typeLabels = Array.from(typeButtons).map(b => ({
                text: b.textContent.trim(),
                type: b.dataset.type,
                active: b.classList.contains('entity-type-btn-active'),
            }));
            const entityTable = document.getElementById('entityTable');
            const searchInput = document.getElementById('entitySearchInput');
            const createBtn = document.querySelector('#entityBrowser .primary-btn');

            return {
                entityBrowserVisible: entityBrowser ? !entityBrowser.classList.contains('hidden') : false,
                companyViewHidden: companyView ? companyView.classList.contains('hidden') : true,
                typeBarExists: !!typeBar,
                typeButtonCount: typeButtons.length,
                typeLabels,
                firstTypeActive: typeLabels.length > 0 ? typeLabels[0].active : false,
                entityTableExists: !!entityTable,
                searchInputExists: !!searchInput,
                createBtnExists: !!createBtn,
                createBtnText: createBtn ? createBtn.textContent.trim() : '',
                schemaActive: typeof _entityBrowserActive !== 'undefined' ? _entityBrowserActive : null,
            };
        });

        record('A1: Entity browser visible (multi-type schema)', browserInfo.entityBrowserVisible);
        record('A2: Company view hidden', browserInfo.companyViewHidden);
        record('A3: Type bar rendered', browserInfo.typeBarExists && browserInfo.typeButtonCount > 0,
            `${browserInfo.typeButtonCount} type buttons: ${browserInfo.typeLabels.map(t => t.type).join(', ')}`);
        record('A4: First type selected by default', browserInfo.firstTypeActive,
            `first type: ${browserInfo.typeLabels.length > 0 ? browserInfo.typeLabels[0].type : 'none'}`);
        record('A5: Entity table exists', browserInfo.entityTableExists);
        record('A6: Search input exists', browserInfo.searchInputExists);
        record('A7: Create button exists', browserInfo.createBtnExists,
            `text="${browserInfo.createBtnText}"`);
        record('A8: Browser active flag set', browserInfo.schemaActive === true,
            `_entityBrowserActive=${browserInfo.schemaActive}`);
    } catch (err) {
        record('A: Entity browser activation', false, err.message);
    }

    // =========================================================================
    // TEST B -- Entity Type Switching
    // =========================================================================
    console.log('\n--- TEST B: Entity Type Switching ---');
    try {
        // Get all type slugs
        const typeSlugs = await page.evaluate(() => {
            return Array.from(document.querySelectorAll('.entity-type-btn')).map(b => b.dataset.type);
        });

        record('B1: Multiple entity types available', typeSlugs.length > 1,
            `types: ${typeSlugs.join(', ')}`);

        if (typeSlugs.length > 1) {
            // Click the second type
            const secondType = typeSlugs[1];
            await page.evaluate((slug) => _setEntityTypeFilter(slug), secondType);
            await page.waitForTimeout(1000);

            const switchInfo = await page.evaluate((slug) => {
                const activeBtn = document.querySelector('.entity-type-btn-active');
                const currentFilter = typeof _entityTypeFilter !== 'undefined' ? _entityTypeFilter : null;
                const thead = document.getElementById('entityTableHead');
                return {
                    activeType: activeBtn ? activeBtn.dataset.type : '',
                    filterValue: currentFilter,
                    headersRendered: thead ? thead.innerHTML.length > 0 : false,
                };
            }, secondType);

            record('B2: Second type button becomes active', switchInfo.activeType === secondType,
                `active="${switchInfo.activeType}", expected="${secondType}"`);
            record('B3: Filter updated to new type', switchInfo.filterValue === secondType,
                `filter="${switchInfo.filterValue}"`);
            record('B4: Table headers re-rendered', switchInfo.headersRendered);

            await page.screenshot({ path: path.join(DIR, 'entity_type_switched.png') });
            console.log('  Screenshot: entity_type_switched.png');

            // Switch back to first type
            await page.evaluate((slug) => _setEntityTypeFilter(slug), typeSlugs[0]);
            await page.waitForTimeout(1000);

            const backInfo = await page.evaluate((slug) => {
                const activeBtn = document.querySelector('.entity-type-btn-active');
                return { activeType: activeBtn ? activeBtn.dataset.type : '' };
            }, typeSlugs[0]);

            record('B5: Can switch back to first type', backInfo.activeType === typeSlugs[0],
                `active="${backInfo.activeType}"`);
        }
    } catch (err) {
        record('B: Type switching', false, err.message);
    }

    // =========================================================================
    // TEST C -- Create Entity via UI Modal
    // =========================================================================
    console.log('\n--- TEST C: Create Entity ---');
    const entityName1 = 'Test Entity Alpha';
    const entityName2 = 'Test Entity Beta';
    let createdEntityId1 = null;
    let createdEntityId2 = null;

    try {
        // Get the current entity type
        const currentType = await page.evaluate(() => _entityTypeFilter);

        // Open the create modal via the + New button
        await page.evaluate(() => openEntityCreateModal());
        await page.waitForTimeout(1000);

        const modalInfo = await page.evaluate(() => {
            const modal = document.getElementById('entityModal');
            const title = document.getElementById('entityModalTitle');
            const nameInput = document.getElementById('entityFormName');
            const body = document.getElementById('entityModalBody');
            // Count form fields (attribute fields generated by schema)
            const formGroups = body ? body.querySelectorAll('.form-group') : [];

            return {
                modalVisible: modal ? !modal.classList.contains('hidden') : false,
                titleText: title ? title.textContent.trim() : '',
                nameInputExists: !!nameInput,
                formGroupCount: formGroups.length,
            };
        });

        record('C1: Create modal opens', modalInfo.modalVisible);
        record('C2: Modal title shows entity type', modalInfo.titleText.includes('New'),
            `title="${modalInfo.titleText}"`);
        record('C3: Name input exists in modal', modalInfo.nameInputExists);
        record('C4: Schema-driven form fields rendered', modalInfo.formGroupCount > 1,
            `${modalInfo.formGroupCount} form groups`);

        await page.screenshot({ path: path.join(DIR, 'entity_create_modal.png') });
        console.log('  Screenshot: entity_create_modal.png');

        // Fill the name and submit
        await page.fill('#entityFormName', entityName1);
        await page.waitForTimeout(300);

        // Click the Create button inside the modal
        await page.evaluate(() => _saveNewEntity());
        await page.waitForTimeout(2000);

        // Check entity appears in the list
        const afterCreate1 = await page.evaluate((name) => {
            const modal = document.getElementById('entityModal');
            const rows = document.querySelectorAll('#entityTableBody tr[data-entity-id]');
            const names = Array.from(rows).map(r => {
                const nameEl = r.querySelector('.entity-name');
                return nameEl ? nameEl.textContent.trim() : '';
            });
            return {
                modalClosed: modal ? modal.classList.contains('hidden') : true,
                rowCount: rows.length,
                entityNames: names,
                hasNewEntity: names.includes(name),
                firstEntityId: rows.length > 0 ? parseInt(rows[0].dataset.entityId) : null,
            };
        }, entityName1);

        record('C5: Modal closed after create', afterCreate1.modalClosed);
        record('C6: Entity appears in table', afterCreate1.hasNewEntity,
            `rows=${afterCreate1.rowCount}, names=[${afterCreate1.entityNames.join(', ')}]`);

        createdEntityId1 = afterCreate1.firstEntityId;

        // Create a second entity via API for later tests
        createdEntityId2 = await page.evaluate(async (args) => {
            const csrf = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
            const r = await fetch('/api/entities', {
                method: 'POST',
                headers: { 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    project_id: args.pid,
                    type: args.type,
                    name: args.name,
                    attributes: {},
                })
            });
            const result = await r.json();
            return result.id || null;
        }, { pid, type: currentType, name: entityName2 });

        record('C7: Second entity created via API', !!createdEntityId2,
            `id=${createdEntityId2}`);

        // Reload entities to show both
        await page.evaluate(() => loadEntities());
        await page.waitForTimeout(1500);

        const afterCreate2 = await page.evaluate(() => {
            const rows = document.querySelectorAll('#entityTableBody tr[data-entity-id]');
            return { rowCount: rows.length };
        });

        record('C8: Both entities in table', afterCreate2.rowCount >= 2,
            `rows=${afterCreate2.rowCount}`);

        await page.screenshot({ path: path.join(DIR, 'entity_list_populated.png') });
        console.log('  Screenshot: entity_list_populated.png');
    } catch (err) {
        record('C: Create entity', false, err.message);
    }

    // =========================================================================
    // TEST D -- Entity Detail Panel
    // =========================================================================
    console.log('\n--- TEST D: Entity Detail Panel ---');
    try {
        // Find the first entity ID from the table
        const entityId = createdEntityId1 || await page.evaluate(() => {
            const row = document.querySelector('#entityTableBody tr[data-entity-id]');
            return row ? parseInt(row.dataset.entityId) : null;
        });

        if (!entityId) {
            record('D: Detail panel (skipped)', false, 'No entities to click');
        } else {
            // Click on entity name to open detail panel
            await page.evaluate((id) => showEntityDetail(id), entityId);
            await page.waitForTimeout(1500);

            await page.screenshot({ path: path.join(DIR, 'entity_detail_panel.png') });
            console.log('  Screenshot: entity_detail_panel.png');

            const detailInfo = await page.evaluate(() => {
                const panel = document.getElementById('entityDetailPanel');
                if (!panel || panel.classList.contains('hidden')) return { visible: false };

                const html = panel.innerHTML;
                const nameEl = panel.querySelector('h2');
                const typeBadge = panel.querySelector('.entity-type-badge');
                const attrSection = html.includes('ATTRIBUTES');
                const editBtn = panel.querySelector('button[onclick*="openEntityEditModal"]');
                const deleteBtn = panel.querySelector('button[onclick*="deleteEntity"]');
                const closeBtn = panel.querySelector('.close-btn');

                return {
                    visible: true,
                    entityName: nameEl ? nameEl.textContent.trim() : '',
                    typeBadge: typeBadge ? typeBadge.textContent.trim() : '',
                    hasAttributeSection: attrSection,
                    hasEditButton: !!editBtn,
                    hasDeleteButton: !!deleteBtn,
                    hasCloseButton: !!closeBtn,
                };
            });

            record('D1: Detail panel opens', detailInfo.visible);
            record('D2: Entity name shown', detailInfo.entityName.length > 0,
                `name="${detailInfo.entityName}"`);
            record('D3: Type badge shown', detailInfo.typeBadge.length > 0,
                `type="${detailInfo.typeBadge}"`);
            record('D4: Attributes section present', detailInfo.hasAttributeSection);
            record('D5: Edit button present', detailInfo.hasEditButton);
            record('D6: Delete button present', detailInfo.hasDeleteButton);
            record('D7: Close button present', detailInfo.hasCloseButton);

            // Close the detail panel
            await page.evaluate(() => closeEntityDetail());
            await page.waitForTimeout(500);

            const panelClosed = await page.evaluate(() => {
                const panel = document.getElementById('entityDetailPanel');
                return panel ? panel.classList.contains('hidden') : true;
            });
            record('D8: Detail panel closes', panelClosed);
        }
    } catch (err) {
        record('D: Detail panel', false, err.message);
    }

    // =========================================================================
    // TEST E -- Edit Entity
    // =========================================================================
    console.log('\n--- TEST E: Edit Entity ---');
    const updatedName = 'Test Entity Alpha EDITED';
    try {
        const entityId = createdEntityId1 || await page.evaluate(() => {
            const row = document.querySelector('#entityTableBody tr[data-entity-id]');
            return row ? parseInt(row.dataset.entityId) : null;
        });

        if (!entityId) {
            record('E: Edit entity (skipped)', false, 'No entity to edit');
        } else {
            // Open edit modal
            await page.evaluate((id) => openEntityEditModal(id), entityId);
            await page.waitForTimeout(1500);

            const editModalInfo = await page.evaluate(() => {
                const modal = document.getElementById('entityModal');
                const title = document.getElementById('entityModalTitle');
                const nameInput = document.getElementById('entityFormName');
                const hiddenId = document.getElementById('entityFormId');
                return {
                    modalVisible: modal ? !modal.classList.contains('hidden') : false,
                    titleText: title ? title.textContent.trim() : '',
                    nameValue: nameInput ? nameInput.value : '',
                    hiddenIdExists: !!hiddenId,
                    hiddenIdValue: hiddenId ? hiddenId.value : '',
                };
            });

            record('E1: Edit modal opens', editModalInfo.modalVisible);
            record('E2: Title says "Edit"', editModalInfo.titleText.includes('Edit'),
                `title="${editModalInfo.titleText}"`);
            record('E3: Name pre-populated', editModalInfo.nameValue.length > 0,
                `value="${editModalInfo.nameValue}"`);
            record('E4: Hidden entity ID set', editModalInfo.hiddenIdExists && editModalInfo.hiddenIdValue.length > 0,
                `id="${editModalInfo.hiddenIdValue}"`);

            await page.screenshot({ path: path.join(DIR, 'entity_edit_modal.png') });
            console.log('  Screenshot: entity_edit_modal.png');

            // Clear and update the name
            await page.fill('#entityFormName', updatedName);
            await page.waitForTimeout(300);

            // Save the edit
            await page.evaluate(() => _saveEditEntity());
            await page.waitForTimeout(2000);

            // Verify the updated name appears in the list
            const afterEdit = await page.evaluate((name) => {
                const modal = document.getElementById('entityModal');
                const rows = document.querySelectorAll('#entityTableBody tr[data-entity-id]');
                const names = Array.from(rows).map(r => {
                    const nameEl = r.querySelector('.entity-name');
                    return nameEl ? nameEl.textContent.trim() : '';
                });
                return {
                    modalClosed: modal ? modal.classList.contains('hidden') : true,
                    hasUpdatedName: names.includes(name),
                    entityNames: names,
                };
            }, updatedName);

            record('E5: Edit modal closed after save', afterEdit.modalClosed);
            record('E6: Updated name appears in table', afterEdit.hasUpdatedName,
                `names=[${afterEdit.entityNames.join(', ')}]`);

            await page.screenshot({ path: path.join(DIR, 'entity_after_edit.png') });
            console.log('  Screenshot: entity_after_edit.png');
        }
    } catch (err) {
        record('E: Edit entity', false, err.message);
    }

    // =========================================================================
    // TEST F -- Entity Search
    // =========================================================================
    console.log('\n--- TEST F: Entity Search ---');
    try {
        const searchInput = await page.$('#entitySearchInput');
        if (!searchInput) {
            record('F: Entity search (skipped)', false, 'entitySearchInput not found');
        } else {
            // Search for "Alpha" (should match the edited entity name)
            await searchInput.fill('');
            await page.waitForTimeout(500);
            await searchInput.fill('EDITED');
            await page.waitForTimeout(1500); // debounce + API call

            const searchResults = await page.evaluate(() => {
                const rows = document.querySelectorAll('#entityTableBody tr[data-entity-id]');
                const names = Array.from(rows).map(r => {
                    const nameEl = r.querySelector('.entity-name');
                    return nameEl ? nameEl.textContent.trim() : '';
                });
                return { count: rows.length, names };
            });

            record('F1: Search filters results', searchResults.count > 0,
                `${searchResults.count} results for "EDITED": ${searchResults.names.join(', ')}`);
            record('F2: Matching entity found', searchResults.names.some(n => n.includes('EDITED')),
                `names=[${searchResults.names.join(', ')}]`);

            // Search for something that should match nothing
            await searchInput.fill('XYZNONEXISTENT999');
            await page.waitForTimeout(1500);

            const noResults = await page.evaluate(() => {
                const rows = document.querySelectorAll('#entityTableBody tr[data-entity-id]');
                const emptyState = document.getElementById('entityEmptyState');
                return {
                    count: rows.length,
                    emptyStateVisible: emptyState ? !emptyState.classList.contains('hidden') : false,
                };
            });

            record('F3: No-match search shows 0 rows', noResults.count === 0,
                `${noResults.count} rows`);
            record('F4: Empty state shown for no results', noResults.emptyStateVisible);

            // Clear search
            await searchInput.fill('');
            await page.waitForTimeout(1500);

            const afterClear = await page.evaluate(() => {
                const rows = document.querySelectorAll('#entityTableBody tr[data-entity-id]');
                return { count: rows.length };
            });

            record('F5: Clearing search restores all entities', afterClear.count >= 2,
                `${afterClear.count} rows after clear`);

            await page.screenshot({ path: path.join(DIR, 'entity_search.png') });
            console.log('  Screenshot: entity_search.png');
        }
    } catch (err) {
        record('F: Entity search', false, err.message);
    }

    // =========================================================================
    // TEST G -- Delete Entity (with confirm dialog)
    // =========================================================================
    console.log('\n--- TEST G: Delete Entity ---');
    try {
        // Count entities before delete
        const beforeDelete = await page.evaluate(() => {
            const rows = document.querySelectorAll('#entityTableBody tr[data-entity-id]');
            return { count: rows.length };
        });

        if (createdEntityId2) {
            // Trigger delete on the second entity
            // deleteEntity uses showNativeConfirm which shows #confirmSheet
            page.evaluate((id) => deleteEntity(id), createdEntityId2);
            await page.waitForTimeout(1000);

            // Check the confirm dialog appeared
            const confirmVisible = await page.evaluate(() => {
                const overlay = document.getElementById('confirmSheet');
                return overlay && overlay.style.display !== 'none';
            });

            record('G1: Confirm dialog appears on delete', confirmVisible);

            await page.screenshot({ path: path.join(DIR, 'entity_delete_confirm.png') });
            console.log('  Screenshot: entity_delete_confirm.png');

            // Click the confirm button
            const didConfirm = await confirmNativeDialog(page);
            await page.waitForTimeout(2000);

            record('G2: Confirm button clicked', didConfirm);

            // Verify entity was removed
            const afterDelete = await page.evaluate(() => {
                const rows = document.querySelectorAll('#entityTableBody tr[data-entity-id]');
                const names = Array.from(rows).map(r => {
                    const nameEl = r.querySelector('.entity-name');
                    return nameEl ? nameEl.textContent.trim() : '';
                });
                return { count: rows.length, names };
            });

            record('G3: Entity count decreased', afterDelete.count < beforeDelete.count,
                `before=${beforeDelete.count}, after=${afterDelete.count}`);
            record('G4: Deleted entity no longer in list',
                !afterDelete.names.includes(entityName2),
                `remaining: [${afterDelete.names.join(', ')}]`);

            await page.screenshot({ path: path.join(DIR, 'entity_after_delete.png') });
            console.log('  Screenshot: entity_after_delete.png');
        } else {
            record('G: Delete entity (skipped)', false, 'No second entity ID');
        }
    } catch (err) {
        record('G: Delete entity', false, err.message);
    }

    // =========================================================================
    // TEST H -- Bulk Selection
    // =========================================================================
    console.log('\n--- TEST H: Bulk Selection ---');
    try {
        // Create a few entities via API for bulk test
        const currentType = await page.evaluate(() => _entityTypeFilter);
        const bulkNames = ['Bulk Test 1', 'Bulk Test 2', 'Bulk Test 3'];
        const bulkIds = [];

        for (const name of bulkNames) {
            const id = await page.evaluate(async (args) => {
                const csrf = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
                const r = await fetch('/api/entities', {
                    method: 'POST',
                    headers: { 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        project_id: args.pid,
                        type: args.type,
                        name: args.name,
                        attributes: {},
                    })
                });
                const result = await r.json();
                return result.id || null;
            }, { pid, type: currentType, name });
            if (id) bulkIds.push(id);
        }

        await page.evaluate(() => loadEntities());
        await page.waitForTimeout(1500);

        // Select all via header checkbox
        const selectAllCheckbox = await page.$('#entityTableHead input[type="checkbox"]');
        if (selectAllCheckbox) {
            await selectAllCheckbox.check();
            await page.waitForTimeout(500);

            const bulkBarInfo = await page.evaluate(() => {
                const bar = document.getElementById('entityBulkBar');
                const count = document.getElementById('entityBulkCount');
                const checkedBoxes = document.querySelectorAll('#entityTableBody input[type="checkbox"]:checked');
                return {
                    barVisible: bar ? !bar.classList.contains('hidden') : false,
                    countText: count ? count.textContent.trim() : '',
                    checkedCount: checkedBoxes.length,
                };
            });

            record('H1: Bulk bar appears on select-all', bulkBarInfo.barVisible);
            record('H2: Bulk count text shown', bulkBarInfo.countText.includes('selected'),
                `text="${bulkBarInfo.countText}"`);
            record('H3: All row checkboxes checked', bulkBarInfo.checkedCount > 0,
                `checked=${bulkBarInfo.checkedCount}`);

            await page.screenshot({ path: path.join(DIR, 'entity_bulk_selected.png') });
            console.log('  Screenshot: entity_bulk_selected.png');

            // Deselect all
            await page.evaluate(() => clearEntityBulkSelection());
            await page.waitForTimeout(500);

            const afterClear = await page.evaluate(() => {
                const bar = document.getElementById('entityBulkBar');
                const checkedBoxes = document.querySelectorAll('#entityTableBody input[type="checkbox"]:checked');
                return {
                    barHidden: bar ? bar.classList.contains('hidden') : true,
                    checkedCount: checkedBoxes.length,
                };
            });

            record('H4: Bulk bar hidden after clear', afterClear.barHidden);
            record('H5: All checkboxes unchecked', afterClear.checkedCount === 0,
                `checked=${afterClear.checkedCount}`);
        } else {
            record('H: Bulk selection (skipped)', false, 'Select-all checkbox not found');
        }
    } catch (err) {
        record('H: Bulk selection', false, err.message);
    }

    // =========================================================================
    // TEST I -- Entity Empty State (switch to type with no entities)
    // =========================================================================
    console.log('\n--- TEST I: Empty State ---');
    try {
        // Get all types and find one that is not the current active type
        const typeInfo = await page.evaluate(() => {
            const buttons = document.querySelectorAll('.entity-type-btn');
            const types = Array.from(buttons).map(b => b.dataset.type);
            const current = _entityTypeFilter;
            const other = types.find(t => t !== current);
            return { types, current, other };
        });

        if (typeInfo.other) {
            // Switch to a type that likely has no entities
            await page.evaluate((slug) => _setEntityTypeFilter(slug), typeInfo.other);
            await page.waitForTimeout(1500);

            const emptyInfo = await page.evaluate(() => {
                const emptyState = document.getElementById('entityEmptyState');
                const table = document.getElementById('entityTable');
                return {
                    emptyStateVisible: emptyState ? !emptyState.classList.contains('hidden') : false,
                    tableHidden: table ? table.classList.contains('hidden') : true,
                    emptyTitle: emptyState ? (emptyState.querySelector('.empty-state-title')?.textContent || '') : '',
                };
            });

            record('I1: Empty state shown for type with no entities', emptyInfo.emptyStateVisible,
                `visible=${emptyInfo.emptyStateVisible}`);
            record('I2: Table hidden when empty', emptyInfo.tableHidden);
            record('I3: Empty state title rendered', emptyInfo.emptyTitle.length > 0,
                `title="${emptyInfo.emptyTitle}"`);

            await page.screenshot({ path: path.join(DIR, 'entity_empty_state.png') });
            console.log('  Screenshot: entity_empty_state.png');

            // Switch back to original type
            await page.evaluate((slug) => _setEntityTypeFilter(slug), typeInfo.current);
            await page.waitForTimeout(1000);
        } else {
            record('I: Empty state (skipped)', false, 'Only one entity type available');
        }
    } catch (err) {
        record('I: Empty state', false, err.message);
    }

    // =========================================================================
    // CLEANUP -- Delete test project (cascades to delete all entities)
    // =========================================================================
    console.log('\n--- Cleanup ---');
    const cleanupCsrf = await getCSRF(page);
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

    // =========================================================================
    // SUMMARY
    // =========================================================================
    console.log('\n' + '='.repeat(60));
    console.log('          ENTITY BROWSER TEST RESULTS');
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
